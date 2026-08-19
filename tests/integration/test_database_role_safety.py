"""Real PostgreSQL evidence for the configured runtime-role boundary."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.utils import timezone
from psycopg import sql
from rest_framework.test import APIClient

from maru.authorization.activation import activate_authority_provenance
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2,
    RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
    RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
    RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS,
    probe_runtime_database_role_safety,
)
from maru.authorization.models import CapabilityGrant
from maru.authorization.policy import (
    decide,
    project_active_authority_scopes,
    resolve_organization_target,
)
from maru.authorization.provenance_readiness import (
    build_authority_provenance_readiness_report,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.organizations.services import (
    OrganizationCreationDetails,
    create_draft_organization,
    update_organization_profile,
)
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
)
from tests.factories import AccountFactory, EventEditionFactory, OrganizationFactory
from tests.support.authority import activate_synthetic_board

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_PAGE9_TRIGGER_HELPER_IDENTITIES = (
    "public.maru_workforce_page9_writer_barrier()",
    "public.maru_workforce_page9_try_scope_mutex(bigint)",
    "public.maru_workforce_page9_scope_mutex()",
    "public.maru_validate_edition_structure_control()",
    "public.maru_assert_edition_structure_control_evidence()",
    "public.maru_prevent_edition_structure_control_mutation()",
    "public.maru_validate_edition_structure_receipt()",
    "public.maru_prevent_edition_structure_receipt_mutation()",
    "public.maru_workforce_department_fk_contract_is_current()",
    "public.maru_validate_department_structure_write()",
    "public.maru_assert_department_structure_evidence()",
    "public.maru_prevent_department_structure_truncate()",
    "public.maru_guard_position_retired_department()",
    "public.maru_guard_assignment_retired_department()",
)

_APPLICATION_DRAFT_CHILD_RELATIONS = (
    "public.applications_applicationownerdepartment",
    "public.applications_applicationreviewerrole",
    "public.applications_applicationreviewerperson",
    "public.applications_applicationsection",
    "public.applications_applicationquestion",
)
_BOUNDED_DOMAIN_PROFILE_REPRESENTATIVES = (
    (
        "public.applications_applicationanswerrevision",
        "INSERT",
        "UPDATE",
    ),
    (
        "public.applications_applicationdefinition",
        "UPDATE",
        "DELETE",
    ),
    (
        "public.charities_charityselectiontimelineentry",
        "INSERT",
        "UPDATE",
    ),
    (
        "public.charities_charitypartner",
        "UPDATE",
        "DELETE",
    ),
    (
        "public.catalog_catalogorderline",
        "INSERT",
        "UPDATE",
    ),
    (
        "public.catalog_editioncatalog",
        "UPDATE",
        "DELETE",
    ),
    (
        "public.venues_venuebookinghistory",
        "INSERT",
        "UPDATE",
    ),
    (
        "public.venues_venueproperty",
        "UPDATE",
        "DELETE",
    ),
)
_BOUNDED_DOMAIN_GRANT_OPTION_REPRESENTATIVES = (
    "public.applications_applicationdefinition",
    "public.charities_charitypartner",
    "public.catalog_editioncatalog",
    "public.venues_venueproperty",
)


def _name(kind: str) -> str:
    return f"maru_probe_{kind}_{uuid4().hex}"


def _create_role(*, login: bool = True, password: str | None = None) -> str:
    role_name = _name("role")
    login_clause = sql.SQL("LOGIN") if login else sql.SQL("NOLOGIN")
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(role_name), login_clause)
        )
    if password is not None:
        assert connection.connection is not None
        # Bypass Django's debug cursor so the bound secret cannot be retained
        # in connection.queries.  psycopg still sends it as a query parameter.
        with connection.connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(role_name)),
                (password,),
            )
    return role_name


def _database_and_user_schemas() -> tuple[str, tuple[str, ...]]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.current_database()")
        database_name = str(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT namespace.nspname
              FROM pg_catalog.pg_namespace AS namespace
             WHERE namespace.nspname <> 'information_schema'
               AND namespace.nspname !~ '^pg_'
             ORDER BY namespace.nspname
            """
        )
        schema_names = tuple(str(row[0]) for row in cursor.fetchall())
    return database_name, schema_names


def _function_privilege_statement(
    *,
    action: str,
    identity: str,
    grantee: sql.Composable,
) -> sql.Composed:
    assert action in {"GRANT", "REVOKE"}
    direction = sql.SQL(" TO ") if action == "GRANT" else sql.SQL(" FROM ")
    return (
        sql.SQL(f"{action} EXECUTE ON FUNCTION ")
        + sql.SQL(identity)
        + direction
        + grantee
    )


def _prepare_least_privilege_boundary() -> None:
    """Remove unsafe PostgreSQL defaults inside the test transaction."""

    database_name, schema_names = _database_and_user_schemas()
    with connection.cursor() as cursor:
        cursor.execute(
            "REVOKE SET, ALTER SYSTEM ON PARAMETER session_replication_role FROM PUBLIC"
        )
        cursor.execute(
            sql.SQL(
                "REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC"
            ).format(sql.Identifier(database_name))
        )
        for schema_name in schema_names:
            schema = sql.Identifier(schema_name)
            cursor.execute(
                sql.SQL("REVOKE CREATE, USAGE ON SCHEMA {} FROM PUBLIC").format(schema)
            )
            cursor.execute(
                sql.SQL(
                    "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC"
                ).format(schema)
            )


def _provision_runtime_role(
    role_name: str,
    *,
    grant_function_allowlist: bool = True,
) -> None:
    """Apply the documented v1 data-plane grants to one synthetic role."""

    database_name, schema_names = _database_and_user_schemas()
    role = sql.Identifier(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database_name),
                role,
            )
        )
        for schema_name in schema_names:
            schema = sql.Identifier(schema_name)
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role)
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE "
                    "ON ALL TABLES IN SCHEMA {} TO {}"
                ).format(schema, role)
            )
            cursor.execute(
                sql.SQL(
                    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}"
                ).format(schema, role)
            )
            cursor.execute(
                sql.SQL("REVOKE UPDATE ON ALL SEQUENCES IN SCHEMA {} FROM {}").format(
                    schema, role
                )
            )
        for identity in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS:
            cursor.execute(
                sql.SQL("REVOKE INSERT, UPDATE, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM ")
                + role
            )
            cursor.execute(
                sql.SQL("REVOKE INSERT, UPDATE, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM PUBLIC")
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + role
            )
        for identity in RUNTIME_DATABASE_SELECT_INSERT_RELATIONS:
            cursor.execute(
                sql.SQL("REVOKE UPDATE, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM ")
                + role
            )
            cursor.execute(
                sql.SQL("REVOKE INSERT, UPDATE, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM PUBLIC")
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + role
            )
        for identity in RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS:
            cursor.execute(
                sql.SQL("REVOKE INSERT, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM ")
                + role
            )
            cursor.execute(
                sql.SQL("REVOKE INSERT, UPDATE, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM PUBLIC")
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, UPDATE ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + role
            )
        for identity in RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS:
            cursor.execute(
                sql.SQL("REVOKE DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM ")
                + role
            )
            cursor.execute(
                sql.SQL("REVOKE INSERT, UPDATE, DELETE, REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" FROM PUBLIC")
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + role
            )
        cursor.execute(
            sql.SQL(
                "REVOKE SET, ALTER SYSTEM ON PARAMETER session_replication_role FROM {}"
            ).format(role)
        )
        if grant_function_allowlist:
            for identity in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2:
                cursor.execute(
                    _function_privilege_statement(
                        action="GRANT",
                        identity=identity,
                        grantee=role,
                    )
                )


def _grant_role(*, parent: str, member: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(parent),
                sql.Identifier(member),
            )
        )


def _provisioning_sql_for_test(
    *,
    migration_role: str,
    runtime_role: str,
    database_name: str,
    break_late_function: bool = False,
    break_required_structure_relation: bool = False,
) -> str:
    artifact_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "operations"
        / "postgresql-runtime-role-provisioning.sql.example"
    )
    statement = artifact_path.read_text(encoding="utf-8")
    statement = statement.replace("maru_migration", migration_role)
    statement = statement.replace("maru_runtime", runtime_role)
    statement = statement.replace(
        "DATABASE maru",
        f"DATABASE {connection.ops.quote_name(database_name)}",
    )
    statement = statement.replace(
        "current_database() <> 'maru'",
        f"current_database() <> '{database_name.replace(chr(39), chr(39) * 2)}'",
    )
    if break_late_function:
        statement = statement.replace(
            "public.maru_workforce_role_evidence_matches_position(",
            "public.maru_missing_role_evidence_matches_position(",
        )
    if break_required_structure_relation:
        statement = statement.replace(
            "public.workforce_editionstructurecommandreceipt",
            "public.maru_missing_editionstructurecommandreceipt",
        )
    return statement


def _public_privilege_snapshot() -> tuple[
    tuple[str, ...],
    dict[str, tuple[str, ...]],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Capture only PUBLIC ACL entries changed by the exact-role rehearsal."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT privilege.privilege_type
              FROM pg_catalog.pg_database AS database
              CROSS JOIN LATERAL pg_catalog.aclexplode(
                  COALESCE(
                      database.datacl,
                      pg_catalog.acldefault(
                          'd'::pg_catalog."char",
                          database.datdba
                      )
                  )
              ) AS privilege
             WHERE database.datname = pg_catalog.current_database()
               AND privilege.grantee = 0
               AND privilege.privilege_type IN (
                   'CONNECT', 'CREATE', 'TEMPORARY'
               )
             ORDER BY privilege.privilege_type
            """
        )
        database_privileges = tuple(str(row[0]) for row in cursor.fetchall())
        cursor.execute(
            """
            SELECT namespace.nspname, privilege.privilege_type
              FROM pg_catalog.pg_namespace AS namespace
              CROSS JOIN LATERAL pg_catalog.aclexplode(
                  COALESCE(
                      namespace.nspacl,
                      pg_catalog.acldefault(
                          'n'::pg_catalog."char",
                          namespace.nspowner
                      )
                  )
              ) AS privilege
             WHERE namespace.nspname <> 'information_schema'
               AND namespace.nspname !~ '^pg_'
               AND privilege.grantee = 0
               AND privilege.privilege_type IN ('CREATE', 'USAGE')
             ORDER BY namespace.nspname, privilege.privilege_type
            """
        )
        schema_privileges: dict[str, list[str]] = {}
        for schema_name, privilege in cursor.fetchall():
            schema_privileges.setdefault(str(schema_name), []).append(str(privilege))
        cursor.execute(
            """
            SELECT procedure.oid::regprocedure::text
              FROM pg_catalog.pg_proc AS procedure
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname <> 'information_schema'
               AND namespace.nspname !~ '^pg_'
               AND EXISTS (
                   SELECT 1
                     FROM pg_catalog.aclexplode(
                         COALESCE(
                             procedure.proacl,
                             pg_catalog.acldefault(
                                 'f'::pg_catalog."char",
                                 procedure.proowner
                             )
                         )
                     ) AS privilege
                    WHERE privilege.grantee = 0
                      AND privilege.privilege_type = 'EXECUTE'
               )
             ORDER BY procedure.oid::regprocedure::text
            """
        )
        function_identities = tuple(str(row[0]) for row in cursor.fetchall())
        cursor.execute(
            """
            SELECT privilege.privilege_type
              FROM pg_catalog.pg_parameter_acl AS parameter
              CROSS JOIN LATERAL pg_catalog.aclexplode(parameter.paracl)
                AS privilege
             WHERE parameter.parname = 'session_replication_role'
               AND privilege.grantee = 0
               AND privilege.privilege_type IN ('SET', 'ALTER SYSTEM')
             ORDER BY privilege.privilege_type
            """
        )
        parameter_privileges = tuple(str(row[0]) for row in cursor.fetchall())
    return (
        database_privileges,
        {key: tuple(value) for key, value in schema_privileges.items()},
        function_identities,
        parameter_privileges,
    )


def _restore_public_privileges(
    snapshot: tuple[
        tuple[str, ...],
        dict[str, tuple[str, ...]],
        tuple[str, ...],
        tuple[str, ...],
    ],
) -> None:
    (
        database_privileges,
        schema_privileges,
        function_identities,
        parameter_privileges,
    ) = snapshot
    database_name, schema_names = _database_and_user_schemas()
    with connection.cursor() as cursor:
        cursor.execute(
            "REVOKE SET, ALTER SYSTEM ON PARAMETER session_replication_role FROM PUBLIC"
        )
        if parameter_privileges:
            cursor.execute(
                sql.SQL(
                    "GRANT {} ON PARAMETER session_replication_role TO PUBLIC"
                ).format(
                    sql.SQL(", ").join(sql.SQL(value) for value in parameter_privileges)
                )
            )
        cursor.execute(
            sql.SQL(
                "REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC"
            ).format(sql.Identifier(database_name))
        )
        if database_privileges:
            cursor.execute(
                sql.SQL("GRANT {} ON DATABASE {} TO PUBLIC").format(
                    sql.SQL(", ").join(sql.SQL(value) for value in database_privileges),
                    sql.Identifier(database_name),
                )
            )
        for schema_name in schema_names:
            schema = sql.Identifier(schema_name)
            cursor.execute(
                sql.SQL("REVOKE CREATE, USAGE ON SCHEMA {} FROM PUBLIC").format(schema)
            )
            privileges = schema_privileges.get(schema_name, ())
            if privileges:
                cursor.execute(
                    sql.SQL("GRANT {} ON SCHEMA {} TO PUBLIC").format(
                        sql.SQL(", ").join(sql.SQL(value) for value in privileges),
                        schema,
                    )
                )
            cursor.execute(
                sql.SQL(
                    "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC"
                ).format(schema)
            )
        for identity in function_identities:
            cursor.execute(
                _function_privilege_statement(
                    action="GRANT",
                    identity=identity,
                    grantee=sql.SQL("PUBLIC"),
                )
            )


@contextmanager
def _password_authenticated_default_database(
    *,
    role_name: str,
    password: str,
) -> Iterator[None]:
    """Reconnect Django's default wrapper as the genuine runtime login."""

    owner_settings = deepcopy(connection.settings_dict)
    connection.close()
    connection.settings_dict.update(
        {"USER": role_name, "PASSWORD": password, "CONN_MAX_AGE": 0}
    )
    try:
        connection.ensure_connection()
        yield
    finally:
        connection.close()
        connection.settings_dict.clear()
        connection.settings_dict.update(owner_settings)
        connection.ensure_connection()


def _sqlstate(error: BaseException) -> str | None:
    cause: BaseException | None = error
    while cause is not None:
        state = getattr(cause, "sqlstate", None)
        if isinstance(state, str):
            return state
        cause = cause.__cause__
    return None


def _table_privilege_matrix(
    *,
    role_name: str,
    identity: str,
) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                pg_catalog.has_table_privilege(%s, %s, 'SELECT'),
                pg_catalog.has_table_privilege(%s, %s, 'INSERT'),
                pg_catalog.has_table_privilege(%s, %s, 'UPDATE'),
                pg_catalog.has_table_privilege(%s, %s, 'DELETE'),
                pg_catalog.has_table_privilege(%s, %s, 'TRUNCATE'),
                pg_catalog.has_table_privilege(%s, %s, 'REFERENCES'),
                pg_catalog.has_table_privilege(%s, %s, 'TRIGGER'),
                pg_catalog.has_table_privilege(%s, %s, 'MAINTAIN')
            """,
            (role_name, identity) * 8,
        )
        row = cursor.fetchone()
    assert row is not None
    return tuple(bool(value) for value in row)  # type: ignore[return-value]


def _assert_structure_relation_privileges(*, role_name: str) -> None:
    for identity in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS:
        assert _table_privilege_matrix(
            role_name=role_name,
            identity=identity,
        ) == (True, False, False, False, False, False, False, False)
    for identity in RUNTIME_DATABASE_SELECT_INSERT_RELATIONS:
        assert _table_privilege_matrix(
            role_name=role_name,
            identity=identity,
        ) == (True, True, False, False, False, False, False, False)
    for identity in RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS:
        assert _table_privilege_matrix(
            role_name=role_name,
            identity=identity,
        ) == (True, False, True, False, False, False, False, False)
    for identity in RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS:
        assert _table_privilege_matrix(
            role_name=role_name,
            identity=identity,
        ) == (True, True, True, False, False, False, False, False)
    department_privileges = _table_privilege_matrix(
        role_name=role_name,
        identity="public.workforce_department",
    )
    assert department_privileges[:4] == (True, True, True, True)
    for identity in _APPLICATION_DRAFT_CHILD_RELATIONS:
        assert _table_privilege_matrix(
            role_name=role_name,
            identity=identity,
        )[:4] == (True, True, True, True)


def _assert_default_table_privileges(
    *,
    migration_role: str,
    runtime_role: str,
) -> None:
    default_table_name = _name("default_acl_table")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(migration_role)))
        try:
            cursor.execute(
                sql.SQL("CREATE TABLE public.{} (id integer)").format(
                    sql.Identifier(default_table_name)
                )
            )
        finally:
            cursor.execute("RESET ROLE")
    assert _table_privilege_matrix(
        role_name=runtime_role,
        identity=f"public.{default_table_name}",
    ) == (True, True, True, True, False, False, False, False)
    assert probe_runtime_database_role_safety(
        role_name=runtime_role
    ).target_role_is_safe


def _assert_runtime_structure_write_plane(
    *,
    edition: EventEdition,
    actor: Account,
) -> None:
    control_id = uuid4()
    receipt_id = uuid4()
    department_id = uuid4()

    with transaction.atomic():
        control = EditionStructureControl.objects.create(
            id=control_id,
            organization=edition.organization,
            edition=edition,
            origin=EditionStructureControl.Origin.MANUAL,
            aggregate_version=1,
        )
        department = Department.objects.create(
            id=department_id,
            organization=edition.organization,
            edition=edition,
            code=f"runtime-boundary-{department_id.hex[:12]}",
            name="Runtime boundary",
            description="Synthetic runtime privilege evidence.",
            created_in_structure_version=1,
            last_changed_in_structure_version=1,
        )
        EditionStructureCommandReceipt.objects.create(
            structure=control,
            organization=edition.organization,
            edition=edition,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
            resulting_version=1,
            actor=actor,
            reason="Create valid runtime structure evidence.",
            correlation_id=uuid4(),
            source_channel="test",
            changed_fields=["departments"],
            affected_department_ids=[department.id],
            retry_key=uuid4(),
            request_digest="a" * 64,
        )
        updated = EditionStructureControl.objects.filter(id=control.id).update(
            aggregate_version=2,
        )
        assert updated == 1
        control.refresh_from_db()
        department.name = "Updated runtime boundary"
        department.last_changed_in_structure_version = 2
        department.save(
            update_fields=("name", "last_changed_in_structure_version", "updated_at")
        )
        receipt = EditionStructureCommandReceipt.objects.create(
            id=receipt_id,
            structure=control,
            organization=edition.organization,
            edition=edition,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
            resulting_version=2,
            actor=actor,
            reason="Verify the runtime structure evidence boundary.",
            correlation_id=uuid4(),
            source_channel="test",
            changed_fields=["name"],
            affected_department_ids=[department.id],
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        stored_control = EditionStructureControl.objects.get(id=control.id)
        assert stored_control.aggregate_version == 2
        assert EditionStructureCommandReceipt.objects.filter(id=receipt.id).exists()

        forbidden_statements = (
            (
                "UPDATE public.workforce_editionstructurecommandreceipt "
                "SET reason = reason WHERE id = %s",
                receipt.id,
            ),
            (
                "DELETE FROM public.workforce_editionstructurecommandreceipt "
                "WHERE id = %s",
                receipt.id,
            ),
            (
                "DELETE FROM public.workforce_editionstructurecontrol WHERE id = %s",
                control.id,
            ),
        )
        for statement, target_id in forbidden_statements:
            with (
                pytest.raises(DatabaseError) as denied,
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, [target_id])
            assert _sqlstate(denied.value) == "42501"

        transaction.set_rollback(True)

    assert not EditionStructureControl.objects.filter(id=control_id).exists()
    assert not EditionStructureCommandReceipt.objects.filter(id=receipt_id).exists()
    assert not Department.objects.filter(id=department_id).exists()


def _assert_protected_relations_are_read_only_for_current_login() -> None:
    for identity in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("SELECT count(*) FROM ") + sql.SQL(identity))
            assert int(cursor.fetchone()[0]) >= 0
            cursor.execute(
                """
                SELECT attribute.attname
                  FROM pg_catalog.pg_attribute AS attribute
                 WHERE attribute.attrelid = pg_catalog.to_regclass(%s)
                   AND attribute.attnum > 0
                   AND NOT attribute.attisdropped
                 ORDER BY attribute.attnum
                 LIMIT 1
                """,
                [identity],
            )
            column_name = str(cursor.fetchone()[0])

        statements = (
            sql.SQL("INSERT INTO ") + sql.SQL(identity) + sql.SQL(" DEFAULT VALUES"),
            (
                sql.SQL("UPDATE ")
                + sql.SQL(identity)
                + sql.SQL(" SET {} = {} WHERE FALSE").format(
                    sql.Identifier(column_name),
                    sql.Identifier(column_name),
                )
            ),
            sql.SQL("DELETE FROM ") + sql.SQL(identity) + sql.SQL(" WHERE FALSE"),
        )
        for statement in statements:
            with pytest.raises(DatabaseError) as denied, connection.cursor() as cursor:
                cursor.execute(statement)
            assert _sqlstate(denied.value) == "42501"


def test_explicit_runtime_data_plane_and_function_allowlist_is_accepted() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert result.target_role_is_safe
    assert result.database_connect_available
    assert result.user_schema_usage_available
    assert result.required_relation_privileges_available
    assert result.sequence_privileges_safe
    assert result.required_sequence_privileges_available
    assert result.parameter_privileges_safe
    assert result.role_settings_safe
    assert result.session_replication_role_is_origin
    assert result.grant_options_safe
    assert result.function_execute_boundary_safe
    assert result.required_function_execute_available
    assert not result.current_user_matches
    assert not result.current_session_is_safe
    _assert_structure_relation_privileges(role_name=role_name)


def test_bounded_domain_relation_catalog_tampering_fails_closed() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)

    for (
        identity,
        required_privilege,
        forbidden_privilege,
    ) in _BOUNDED_DOMAIN_PROFILE_REPRESENTATIVES:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("REVOKE ")
                    + sql.SQL(required_privilege)
                    + sql.SQL(" ON TABLE ")
                    + sql.SQL(identity)
                    + sql.SQL(" FROM ")
                    + sql.Identifier(role_name)
                )
            missing = probe_runtime_database_role_safety(role_name=role_name)
            assert not missing.required_relation_privileges_available
            assert not missing.target_role_is_safe
            transaction.set_rollback(True)
        assert probe_runtime_database_role_safety(
            role_name=role_name
        ).target_role_is_safe

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("GRANT ")
                    + sql.SQL(forbidden_privilege)
                    + sql.SQL(" ON TABLE ")
                    + sql.SQL(identity)
                    + sql.SQL(" TO ")
                    + sql.Identifier(role_name)
                )
            excessive = probe_runtime_database_role_safety(role_name=role_name)
            assert not excessive.required_relation_privileges_available
            assert not excessive.target_role_is_safe
            transaction.set_rollback(True)
        assert probe_runtime_database_role_safety(
            role_name=role_name
        ).target_role_is_safe


def test_bounded_domain_relation_grant_options_fail_closed() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)

    for identity in _BOUNDED_DOMAIN_GRANT_OPTION_REPRESENTATIVES:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("GRANT SELECT ON TABLE ")
                    + sql.SQL(identity)
                    + sql.SQL(" TO ")
                    + sql.Identifier(role_name)
                    + sql.SQL(" WITH GRANT OPTION")
                )
            result = probe_runtime_database_role_safety(role_name=role_name)
            assert not result.grant_options_safe
            assert not result.target_role_is_safe
            transaction.set_rollback(True)
        assert probe_runtime_database_role_safety(
            role_name=role_name
        ).target_role_is_safe


def test_bounded_domain_excess_mutation_privilege_blocks_activation_readiness() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)

    with override_settings(RUNTIME_DATABASE_ROLE=role_name):
        baseline = build_authority_provenance_readiness_report()
        assert baseline["known_production_gates"]["runtime_database_role"] == (
            "resolved"
        )
        for identity in _BOUNDED_DOMAIN_GRANT_OPTION_REPRESENTATIVES:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("GRANT DELETE ON TABLE ")
                        + sql.SQL(identity)
                        + sql.SQL(" TO ")
                        + sql.Identifier(role_name)
                    )
                unavailable = build_authority_provenance_readiness_report()
                assert (
                    unavailable["known_production_gates"]["runtime_database_role"]
                    == "unresolved"
                )
                transaction.set_rollback(True)


def test_page9_trigger_helpers_do_not_expand_runtime_execute_closure() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)

    assert not set(_PAGE9_TRIGGER_HELPER_IDENTITIES) & set(
        RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT required.identity,
                   procedure.prosecdef,
                   pg_catalog.has_function_privilege(
                       %s,
                       procedure.oid,
                       'EXECUTE'
                   ),
                   EXISTS (
                       SELECT 1
                         FROM pg_catalog.aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault(
                                     'f'::pg_catalog."char",
                                     procedure.proowner
                                 )
                             )
                         ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                   )
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(required.identity)
             ORDER BY required.identity
            """,
            [role_name, list(_PAGE9_TRIGGER_HELPER_IDENTITIES)],
        )
        rows = cursor.fetchall()

    assert len(rows) == len(_PAGE9_TRIGGER_HELPER_IDENTITIES)
    assert all(
        security_definer and not runtime_execute and not public_execute
        for _, security_definer, runtime_execute, public_execute in rows
    )
    result = probe_runtime_database_role_safety(role_name=role_name)
    assert result.target_role_is_safe
    assert result.function_execute_boundary_safe
    assert result.required_function_execute_available


@pytest.mark.parametrize(
    "attribute",
    ["SUPERUSER", "CREATEDB", "CREATEROLE", "REPLICATION", "BYPASSRLS"],
)
def test_dangerous_role_attributes_are_rejected(attribute: str) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER ROLE {} WITH ").format(sql.Identifier(role_name))
            + sql.SQL(attribute)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.attributes_safe
    assert not result.target_role_is_safe


def test_missing_and_non_login_roles_are_rejected() -> None:
    _prepare_least_privilege_boundary()
    no_login_role = _create_role(login=False)
    _provision_runtime_role(no_login_role)

    missing = probe_runtime_database_role_safety(role_name=_name("missing"))
    no_login = probe_runtime_database_role_safety(role_name=no_login_role)

    assert not missing.role_exists
    assert not missing.target_role_is_safe
    assert no_login.role_exists
    assert not no_login.can_login
    assert not no_login.target_role_is_safe


def test_predefined_and_custom_dangerous_role_memberships_are_rejected() -> None:
    _prepare_least_privilege_boundary()
    predefined_member = _create_role()
    custom_member = _create_role()
    dangerous_parent = _create_role(login=False)
    _provision_runtime_role(predefined_member)
    _provision_runtime_role(custom_member)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER ROLE {} CREATEDB").format(sql.Identifier(dangerous_parent))
        )
    _grant_role(parent="pg_read_all_data", member=predefined_member)
    _grant_role(parent=dangerous_parent, member=custom_member)

    predefined = probe_runtime_database_role_safety(role_name=predefined_member)
    custom = probe_runtime_database_role_safety(role_name=custom_member)

    assert not predefined.memberships_safe
    assert not predefined.target_role_is_safe
    assert not custom.attributes_safe
    assert not custom.memberships_safe
    assert not custom.target_role_is_safe


def test_reachable_membership_admin_option_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    delegable_parent = _create_role(login=False)
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT {} TO {} WITH ADMIN OPTION").format(
                sql.Identifier(delegable_parent),
                sql.Identifier(role_name),
            )
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.memberships_safe
    assert not result.target_role_is_safe


def test_database_and_user_schema_ownership_or_create_paths_are_rejected() -> None:
    _prepare_least_privilege_boundary()
    database_owner_member = _create_role()
    schema_owner_member = _create_role()
    schema_creator = _create_role()
    schema_owner = _create_role(login=False)
    for role_name in (
        database_owner_member,
        schema_owner_member,
        schema_creator,
    ):
        _provision_runtime_role(role_name)
    owned_schema = _name("owned_schema")
    grant_schema = _name("grant_schema")
    with connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_USER")
        database_owner = str(cursor.fetchone()[0])
        cursor.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                sql.Identifier(owned_schema),
                sql.Identifier(schema_owner),
            )
        )
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(grant_schema)))
        cursor.execute(
            sql.SQL("GRANT CREATE ON SCHEMA {} TO {}").format(
                sql.Identifier(grant_schema),
                sql.Identifier(schema_creator),
            )
        )
    _grant_role(parent=database_owner, member=database_owner_member)
    _grant_role(parent=schema_owner, member=schema_owner_member)

    database_result = probe_runtime_database_role_safety(
        role_name=database_owner_member
    )
    schema_owner_result = probe_runtime_database_role_safety(
        role_name=schema_owner_member
    )
    schema_create_result = probe_runtime_database_role_safety(role_name=schema_creator)

    assert not database_result.database_ownership_safe
    assert not database_result.target_role_is_safe
    assert not schema_owner_result.user_schema_ownership_safe
    assert not schema_owner_result.target_role_is_safe
    assert not schema_create_result.user_schema_privileges_safe
    assert not schema_create_result.target_role_is_safe


def test_user_relation_and_function_owner_memberships_are_rejected() -> None:
    _prepare_least_privilege_boundary()
    relation_member = _create_role()
    function_member = _create_role()
    relation_owner = _create_role(login=False)
    function_owner = _create_role(login=False)
    _provision_runtime_role(relation_member)
    _provision_runtime_role(function_member)
    table_name = _name("table")
    function_name = _name("function")
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE TABLE public.{} (id integer)").format(
                sql.Identifier(table_name)
            )
        )
        cursor.execute(
            sql.SQL("ALTER TABLE public.{} OWNER TO {}").format(
                sql.Identifier(table_name),
                sql.Identifier(relation_owner),
            )
        )
        cursor.execute(
            sql.SQL(
                "CREATE FUNCTION public.{}() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
            ).format(sql.Identifier(function_name))
        )
        cursor.execute(
            sql.SQL("ALTER FUNCTION public.{}() OWNER TO {}").format(
                sql.Identifier(function_name),
                sql.Identifier(function_owner),
            )
        )
    _grant_role(parent=relation_owner, member=relation_member)
    _grant_role(parent=function_owner, member=function_member)

    relation_result = probe_runtime_database_role_safety(role_name=relation_member)
    function_result = probe_runtime_database_role_safety(role_name=function_member)

    assert not relation_result.user_relation_ownership_safe
    assert not relation_result.target_role_is_safe
    assert not function_result.user_function_ownership_safe
    assert not function_result.target_role_is_safe


@pytest.mark.parametrize("privilege", ["TRIGGER", "TRUNCATE", "MAINTAIN"])
def test_unsafe_table_privileges_are_rejected(privilege: str) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT ")
            + sql.SQL(privilege)
            + sql.SQL(" ON TABLE public.django_migrations TO ")
            + sql.Identifier(role_name)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.table_privileges_safe
    assert not result.target_role_is_safe


@pytest.mark.parametrize("privilege", ["CREATE", "TEMPORARY"])
def test_unsafe_database_privileges_are_rejected(privilege: str) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    database_name, _schema_names = _database_and_user_schemas()
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT ")
            + sql.SQL(privilege)
            + sql.SQL(" ON DATABASE ")
            + sql.Identifier(database_name)
            + sql.SQL(" TO ")
            + sql.Identifier(role_name)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.database_privileges_safe
    assert not result.target_role_is_safe


def test_public_only_function_execute_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name, grant_function_allowlist=False)
    with connection.cursor() as cursor:
        for identity in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2:
            cursor.execute(
                _function_privilege_statement(
                    action="GRANT",
                    identity=identity,
                    grantee=sql.SQL("PUBLIC"),
                )
            )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert result.required_function_execute_available
    assert not result.function_execute_boundary_safe
    assert not result.target_role_is_safe


def test_every_required_function_needs_explicit_effective_execute() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    denied_identity = RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2[-1]
    with connection.cursor() as cursor:
        cursor.execute(
            _function_privilege_statement(
                action="REVOKE",
                identity=denied_identity,
                grantee=sql.Identifier(role_name),
            )
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert result.function_execute_boundary_safe
    assert not result.required_function_execute_available
    assert not result.target_role_is_safe


def test_execute_outside_the_versioned_allowlist_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.maru_guard_audit_event() TO {}"
            ).format(sql.Identifier(role_name))
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.function_execute_boundary_safe
    assert not result.target_role_is_safe


def test_set_role_reachable_unallowlisted_execute_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    function_executor = _create_role(login=False)
    _provision_runtime_role(role_name)
    unallowlisted_identity = "public.maru_guard_audit_event()"
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER ROLE {} NOINHERIT").format(sql.Identifier(role_name))
        )
        cursor.execute(
            _function_privilege_statement(
                action="GRANT",
                identity=unallowlisted_identity,
                grantee=sql.Identifier(function_executor),
            )
        )
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(function_executor)
            )
        )
        cursor.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                sql.Identifier(function_executor),
                sql.Identifier(role_name),
            )
        )
        cursor.execute(
            """
            SELECT membership.inherit_option, membership.set_option
              FROM pg_catalog.pg_auth_members AS membership
              JOIN pg_catalog.pg_roles AS parent
                ON parent.oid = membership.roleid
              JOIN pg_catalog.pg_roles AS member
                ON member.oid = membership.member
             WHERE parent.rolname = %s
               AND member.rolname = %s
            """,
            (function_executor, role_name),
        )
        assert cursor.fetchone() == (False, True)
        cursor.execute(
            "SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')",
            (role_name, unallowlisted_identity),
        )
        assert cursor.fetchone() == (False,)
        cursor.execute(
            sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(function_executor))
        )
        cursor.execute(
            "SELECT pg_catalog.has_function_privilege(CURRENT_USER, %s, 'EXECUTE')",
            (unallowlisted_identity,),
        )
        assert cursor.fetchone() == (True,)
        cursor.execute("RESET ROLE")

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert result.memberships_safe
    assert not result.function_execute_boundary_safe
    assert not result.target_role_is_safe


def test_missing_database_connect_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    database_name, _schema_names = _database_and_user_schemas()
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(database_name),
                sql.Identifier(role_name),
            )
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.database_connect_available
    assert not result.target_role_is_safe


def test_missing_user_schema_usage_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(
                sql.Identifier(role_name)
            )
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.user_schema_usage_available
    assert not result.target_role_is_safe


def test_missing_required_relation_dml_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("REVOKE DELETE ON TABLE public.events_eventedition FROM {}").format(
                sql.Identifier(role_name)
            )
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.required_relation_privileges_available
    assert not result.target_role_is_safe


@pytest.mark.parametrize(
    ("identity", "privilege"),
    [
        (RUNTIME_DATABASE_SELECT_INSERT_RELATIONS[0], "INSERT"),
        (RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS[0], "UPDATE"),
        (RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS[0], "INSERT"),
        (RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS[0], "UPDATE"),
    ],
)
def test_missing_required_structure_relation_privilege_is_rejected(
    identity: str,
    privilege: str,
) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("REVOKE ")
            + sql.SQL(privilege)
            + sql.SQL(" ON TABLE ")
            + sql.SQL(identity)
            + sql.SQL(" FROM ")
            + sql.Identifier(role_name)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.required_relation_privileges_available
    assert not result.target_role_is_safe


@pytest.mark.parametrize(
    ("identity", "privilege", "column_level"),
    [
        (RUNTIME_DATABASE_SELECT_INSERT_RELATIONS[0], "UPDATE", False),
        (RUNTIME_DATABASE_SELECT_INSERT_RELATIONS[0], "UPDATE", True),
        (RUNTIME_DATABASE_SELECT_INSERT_RELATIONS[0], "DELETE", False),
        (RUNTIME_DATABASE_SELECT_INSERT_RELATIONS[0], "REFERENCES", False),
        (RUNTIME_DATABASE_SELECT_INSERT_RELATIONS[0], "REFERENCES", True),
        (RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS[0], "INSERT", False),
        (RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS[0], "INSERT", True),
        (RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS[0], "DELETE", False),
        (RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS[0], "REFERENCES", False),
        (RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS[0], "REFERENCES", True),
        (RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS[0], "DELETE", False),
        (RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS[0], "REFERENCES", False),
        (RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS[0], "REFERENCES", True),
    ],
)
def test_forbidden_structure_relation_privilege_is_rejected(
    identity: str,
    privilege: str,
    column_level: bool,
) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        if column_level:
            cursor.execute(
                """
                SELECT attribute.attname
                  FROM pg_catalog.pg_attribute AS attribute
                 WHERE attribute.attrelid = pg_catalog.to_regclass(%s)
                   AND attribute.attnum > 0
                   AND NOT attribute.attisdropped
                 ORDER BY attribute.attnum
                 LIMIT 1
                """,
                [identity],
            )
            column_name = str(cursor.fetchone()[0])
            cursor.execute(
                sql.SQL("GRANT {} ({}) ON TABLE ").format(
                    sql.SQL(privilege),
                    sql.Identifier(column_name),
                )
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + sql.Identifier(role_name)
            )
        else:
            cursor.execute(
                sql.SQL("GRANT ")
                + sql.SQL(privilege)
                + sql.SQL(" ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + sql.Identifier(role_name)
            )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.required_relation_privileges_available
    assert not result.target_role_is_safe


@pytest.mark.parametrize(
    "identity",
    [
        *RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
        *RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS,
        *RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
    ],
)
@pytest.mark.parametrize("privilege", ["TRIGGER", "TRUNCATE"])
def test_structure_relation_control_plane_privilege_is_rejected(
    identity: str,
    privilege: str,
) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT ")
            + sql.SQL(privilege)
            + sql.SQL(" ON TABLE ")
            + sql.SQL(identity)
            + sql.SQL(" TO ")
            + sql.Identifier(role_name)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.table_privileges_safe
    assert not result.target_role_is_safe


def test_department_remains_on_the_ordinary_runtime_dml_plane() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)

    _assert_structure_relation_privileges(role_name=role_name)

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "REVOKE DELETE ON TABLE public.workforce_department FROM {}"
            ).format(sql.Identifier(role_name))
        )
    result = probe_runtime_database_role_safety(role_name=role_name)
    assert not result.required_relation_privileges_available
    assert not result.target_role_is_safe


@pytest.mark.parametrize("identity", RUNTIME_DATABASE_SELECT_ONLY_RELATIONS)
@pytest.mark.parametrize("column_level", [False, True])
def test_protected_relation_mutation_privileges_are_rejected(
    identity: str,
    column_level: bool,
) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        if column_level:
            cursor.execute(
                """
                SELECT attribute.attname
                  FROM pg_catalog.pg_attribute AS attribute
                 WHERE attribute.attrelid = pg_catalog.to_regclass(%s)
                   AND attribute.attnum > 0
                   AND NOT attribute.attisdropped
                 ORDER BY attribute.attnum
                 LIMIT 1
                """,
                [identity],
            )
            column_name = str(cursor.fetchone()[0])
            cursor.execute(
                sql.SQL("GRANT INSERT ({}), UPDATE ({}) ON TABLE ").format(
                    sql.Identifier(column_name), sql.Identifier(column_name)
                )
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + sql.Identifier(role_name)
            )
        else:
            cursor.execute(
                sql.SQL("GRANT INSERT, UPDATE, DELETE ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + sql.Identifier(role_name)
            )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.required_relation_privileges_available
    assert not result.target_role_is_safe


@pytest.mark.parametrize("identity", RUNTIME_DATABASE_SELECT_ONLY_RELATIONS)
@pytest.mark.parametrize(
    "grant_path",
    ["table", "column", "inherited", "public"],
)
def test_protected_relation_references_privilege_is_rejected(
    identity: str,
    grant_path: str,
) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    grantee: sql.Composable = sql.Identifier(role_name)
    with connection.cursor() as cursor:
        if grant_path == "public":
            grantee = sql.SQL("PUBLIC")
        elif grant_path == "inherited":
            inherited_role = _create_role(login=False)
            _grant_role(parent=inherited_role, member=role_name)
            grantee = sql.Identifier(inherited_role)

        if grant_path == "column":
            cursor.execute(
                """
                SELECT attribute.attname
                  FROM pg_catalog.pg_attribute AS attribute
                 WHERE attribute.attrelid = pg_catalog.to_regclass(%s)
                   AND attribute.attnum > 0
                   AND NOT attribute.attisdropped
                 ORDER BY attribute.attnum
                 LIMIT 1
                """,
                [identity],
            )
            column_name = str(cursor.fetchone()[0])
            cursor.execute(
                sql.SQL("GRANT REFERENCES ({}) ON TABLE ").format(
                    sql.Identifier(column_name)
                )
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + grantee
            )
        else:
            cursor.execute(
                sql.SQL("GRANT REFERENCES ON TABLE ")
                + sql.SQL(identity)
                + sql.SQL(" TO ")
                + grantee
            )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.required_relation_privileges_available
    assert not result.target_role_is_safe


def test_missing_required_sequence_privilege_is_rejected() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relation.oid::regclass::text
              FROM pg_catalog.pg_class AS relation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND relation.relkind = 'S'
             ORDER BY relation.oid
             LIMIT 1
            """
        )
        row = cursor.fetchone()
        assert row is not None
        sequence_identity = str(row[0])
        cursor.execute(
            sql.SQL("REVOKE SELECT ON SEQUENCE ")
            + sql.SQL(sequence_identity)
            + sql.SQL(" FROM ")
            + sql.Identifier(role_name)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.required_sequence_privileges_available
    assert not result.target_role_is_safe


def test_sequence_update_is_rejected_while_usage_and_select_remain_available() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relation.oid::regclass::text
              FROM pg_catalog.pg_class AS relation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND relation.relkind = 'S'
             ORDER BY relation.oid
             LIMIT 1
            """
        )
        sequence_identity = str(cursor.fetchone()[0])
        cursor.execute(
            sql.SQL("GRANT UPDATE ON SEQUENCE ")
            + sql.SQL(sequence_identity)
            + sql.SQL(" TO ")
            + sql.Identifier(role_name)
        )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.sequence_privileges_safe
    assert result.required_sequence_privileges_available
    assert not result.target_role_is_safe


@pytest.mark.parametrize(
    "object_kind",
    ["database", "schema", "table", "column", "sequence", "function"],
)
def test_representative_object_grant_options_are_rejected(
    object_kind: str,
) -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        if object_kind == "database":
            database_name, _schema_names = _database_and_user_schemas()
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {} WITH GRANT OPTION").format(
                    sql.Identifier(database_name),
                    sql.Identifier(role_name),
                )
            )
        elif object_kind == "schema":
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {} WITH GRANT OPTION").format(
                    sql.Identifier(role_name)
                )
            )
        elif object_kind == "table":
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON TABLE public.django_migrations TO {} "
                    "WITH GRANT OPTION"
                ).format(sql.Identifier(role_name))
            )
        elif object_kind == "column":
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT (id) ON TABLE public.django_migrations "
                    "TO {} WITH GRANT OPTION"
                ).format(sql.Identifier(role_name))
            )
        elif object_kind == "sequence":
            cursor.execute(
                """
                SELECT relation.oid::regclass::text
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                 WHERE namespace.nspname = 'public'
                   AND relation.relkind = 'S'
                 ORDER BY relation.oid
                 LIMIT 1
                """
            )
            sequence_identity = str(cursor.fetchone()[0])
            cursor.execute(
                sql.SQL("GRANT USAGE ON SEQUENCE ")
                + sql.SQL(sequence_identity)
                + sql.SQL(" TO ")
                + sql.Identifier(role_name)
                + sql.SQL(" WITH GRANT OPTION")
            )
        else:
            cursor.execute(
                _function_privilege_statement(
                    action="GRANT",
                    identity=RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2[0],
                    grantee=sql.Identifier(role_name),
                )
                + sql.SQL(" WITH GRANT OPTION")
            )

    result = probe_runtime_database_role_safety(role_name=role_name)

    assert not result.grant_options_safe
    assert not result.target_role_is_safe


def test_parameter_set_acl_is_rejected_and_can_suppress_integrity_triggers() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    table_name = _name("trigger_sentinel")
    function_name = _name("trigger_sentinel")
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE TABLE public.{} "
                "(id integer, trigger_ran boolean NOT NULL DEFAULT FALSE)"
            ).format(sql.Identifier(table_name))
        )
        cursor.execute(
            sql.SQL(
                "CREATE FUNCTION public.{}() RETURNS trigger "
                "LANGUAGE plpgsql AS "
                "'BEGIN NEW.trigger_ran := TRUE; RETURN NEW; END'"
            ).format(sql.Identifier(function_name))
        )
        cursor.execute(
            sql.SQL(
                "CREATE TRIGGER maru_probe_trigger BEFORE INSERT ON public.{} "
                "FOR EACH ROW EXECUTE FUNCTION public.{}()"
            ).format(sql.Identifier(table_name), sql.Identifier(function_name))
        )
        cursor.execute(
            sql.SQL("REVOKE EXECUTE ON FUNCTION public.{}() FROM PUBLIC").format(
                sql.Identifier(function_name)
            )
        )
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{} TO {}"
            ).format(sql.Identifier(table_name), sql.Identifier(role_name))
        )
        cursor.execute(
            sql.SQL("GRANT SET ON PARAMETER session_replication_role TO {}").format(
                sql.Identifier(role_name)
            )
        )

    result = probe_runtime_database_role_safety(role_name=role_name)
    assert not result.parameter_privileges_safe
    assert not result.target_role_is_safe

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
        try:
            cursor.execute("SET LOCAL session_replication_role = replica")
            cursor.execute(
                sql.SQL("INSERT INTO public.{} (id) VALUES (1)").format(
                    sql.Identifier(table_name)
                )
            )
        finally:
            cursor.execute("SET LOCAL session_replication_role = origin")
            cursor.execute("RESET ROLE")
        cursor.execute(
            sql.SQL("SELECT trigger_ran FROM public.{} WHERE id = 1").format(
                sql.Identifier(table_name)
            )
        )
        assert cursor.fetchone() == (False,)


def test_set_role_proves_privileges_but_not_authenticated_runtime_session() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
    try:
        result = probe_runtime_database_role_safety(role_name=role_name)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")

    assert result.target_role_is_safe
    assert result.current_user_matches
    assert not result.session_user_matches
    assert not result.authenticated_user_matches
    assert not result.current_session_is_safe


def test_set_session_authorization_cannot_impersonate_authenticated_login() -> None:
    _prepare_least_privilege_boundary()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SET LOCAL SESSION AUTHORIZATION {}").format(
                sql.Identifier(role_name)
            )
        )
    try:
        result = probe_runtime_database_role_safety(role_name=role_name)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET SESSION AUTHORIZATION")

    assert result.target_role_is_safe
    assert result.current_user_matches
    assert result.session_user_matches
    assert not result.authenticated_user_matches
    assert not result.current_session_is_safe


def test_set_role_runtime_smoke_supports_real_services_and_trigger_helpers() -> None:
    _prepare_least_privilege_boundary()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    principal = AccountFactory()
    grant_actor = AccountFactory()
    grant_approver = AccountFactory()
    role_name = _create_role()
    _provision_runtime_role(role_name)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
    try:
        session_result = probe_runtime_database_role_safety(role_name=role_name)
        assert session_result.target_role_is_safe
        assert not session_result.current_session_is_safe
        organization = create_draft_organization(
            actor=administrator,
            details=OrganizationCreationDetails(name="Runtime Role Smoke"),
            correlation_id=uuid4(),
            source_channel="test",
        )
        result = update_organization_profile(
            actor=administrator,
            organization_id=organization.id,
            details=OrganizationCreationDetails(
                name=organization.name,
                description="Updated through the provisioned runtime role.",
            ),
            correlation_id=uuid4(),
            source_channel="test",
        )
        grant = CapabilityGrant.objects.create(
            organization=organization,
            principal=principal,
            capability_code="organizations.view_basic",
            effective_from=timezone.now(),
            granted_by=grant_actor,
            approved_by=grant_approver,
            reason="Exercise runtime trigger helper execution.",
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        assert result.changed_fields == ("description",)
        assert Organization.objects.get(id=organization.id).description.startswith(
            "Updated"
        )
        assert CapabilityGrant.objects.filter(id=grant.id).exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


@pytest.mark.django_db(transaction=True)
def test_exact_mode_set_role_supports_decision_and_batched_issuance_reads() -> None:
    """Prove the active v1 policy/helper closure through the real target role."""

    organization = OrganizationFactory()
    controller, _approver = activate_synthetic_board(organization)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    public_snapshot = _public_privilege_snapshot()
    role_name = _create_role()
    try:
        with transaction.atomic():
            _prepare_least_privilege_boundary()
            _provision_runtime_role(role_name)
        with override_settings(
            REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
            RUNTIME_DATABASE_ROLE=role_name,
        ):
            activation = activate_authority_provenance(
                actor=administrator,
                reason="Exercise the configured runtime role in exact mode.",
                correlation_id=uuid4(),
                acknowledge_processes_stopped=True,
                source_channel="test",
            )
            assert activation.activated

            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name))
                )
                session_result = probe_runtime_database_role_safety(role_name=role_name)
                assert session_result.target_role_is_safe
                assert not session_result.current_session_is_safe
                decision = decide(
                    principal=controller,
                    capability_code="organizations.view_basic",
                    resource=target,
                )
                projections = project_active_authority_scopes(principal=controller)

            assert decision.allowed
            assert any(
                projection.organization_id == organization.id
                and "organizations.view_basic" in projection.capability_codes
                for projection in projections
            )
    finally:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
            )
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
            _restore_public_privileges(public_snapshot)


@pytest.mark.django_db(transaction=True)
def test_genuine_runtime_login_is_safe_and_persistent_replica_setting_is_not() -> None:  # noqa: PLR0915
    """Prove genuine login, protected reads, and persistent-setting failure."""

    organization = OrganizationFactory()
    controller, _approver = activate_synthetic_board(organization)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    structure_edition = EventEditionFactory()
    structure_actor = AccountFactory()
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    public_snapshot = _public_privilege_snapshot()
    password = secrets.token_urlsafe(36)
    wrong_password = secrets.token_urlsafe(36)
    role_name = _create_role(password=password)
    credential_was_logged = False
    database_name, _schema_names = _database_and_user_schemas()
    try:
        with transaction.atomic():
            _prepare_least_privilege_boundary()
            _provision_runtime_role(role_name)

        with override_settings(
            REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
            RUNTIME_DATABASE_ROLE=role_name,
        ):
            activation = activate_authority_provenance(
                actor=administrator,
                reason="Prove the genuine runtime login boundary.",
                correlation_id=uuid4(),
                acknowledge_processes_stopped=True,
                source_channel="test",
            )
            assert activation.activated

            with (
                pytest.raises(DatabaseError),
                _password_authenticated_default_database(
                    role_name=role_name,
                    password=wrong_password,
                ),
            ):
                pass
            # libpq does not expose SQLSTATE 28P01 on every startup-authentication
            # failure, so the rejected connection itself is the portable proof
            # that the local pg_hba path is not passwordless trust.
            assert connection.connection is not None
            credential_was_logged |= any(
                wrong_password in str(entry.get("sql", ""))
                for entry in connection.queries
            )

            with _password_authenticated_default_database(
                role_name=role_name,
                password=password,
            ):
                session_result = probe_runtime_database_role_safety(role_name=role_name)
                assert session_result.target_role_is_safe
                assert session_result.current_user_matches
                assert session_result.session_user_matches
                assert session_result.authenticated_user_matches
                assert session_result.current_session_is_safe
                _assert_protected_relations_are_read_only_for_current_login()
                _assert_structure_relation_privileges(role_name=role_name)
                _assert_runtime_structure_write_plane(
                    edition=structure_edition,
                    actor=structure_actor,
                )
                readiness_response = APIClient().get("/health/ready")
                assert readiness_response.status_code == 200
                assert readiness_response.json() == {
                    "status": "ok",
                    "dependencies": {
                        "database": "ok",
                        "authority_provenance": "ok",
                        "applications_integrity": "ok",
                        "charities_integrity": "ok",
                        "catalog_integrity": "ok",
                        "venues_integrity": "ok",
                        "logistics": "ok",
                    },
                }

                decision = decide(
                    principal=controller,
                    capability_code="organizations.view_basic",
                    resource=target,
                )
                projections = project_active_authority_scopes(principal=controller)
                assert decision.allowed
                assert any(
                    projection.organization_id == organization.id
                    and "organizations.view_basic" in projection.capability_codes
                    for projection in projections
                )
                credential_was_logged |= any(
                    password in str(entry.get("sql", ""))
                    for entry in connection.queries
                )

            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} IN DATABASE {} "
                        "SET session_replication_role = replica"
                    ).format(
                        sql.Identifier(role_name),
                        sql.Identifier(database_name),
                    )
                )

            with _password_authenticated_default_database(
                role_name=role_name,
                password=password,
            ):
                unsafe = probe_runtime_database_role_safety(role_name=role_name)
                assert unsafe.current_user_matches
                assert unsafe.session_user_matches
                assert unsafe.authenticated_user_matches
                assert not unsafe.role_settings_safe
                assert not unsafe.session_replication_role_is_origin
                assert not unsafe.target_role_is_safe
                assert not unsafe.current_session_is_safe
                credential_was_logged |= any(
                    password in str(entry.get("sql", ""))
                    for entry in connection.queries
                )

        assert not credential_was_logged
    finally:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} IN DATABASE {} RESET session_replication_role"
                ).format(
                    sql.Identifier(role_name),
                    sql.Identifier(database_name),
                )
            )
            cursor.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
            )
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
            _restore_public_privileges(public_snapshot)


@pytest.mark.django_db(transaction=True)
def test_provisioning_requires_the_page9_structure_migration_first() -> None:
    """A missing restricted relation aborts role and global ACL changes."""

    public_snapshot = _public_privilege_snapshot()
    database_name, _schema_names = _database_and_user_schemas()
    migration_role = _name("migration")
    runtime_role = _name("runtime")
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(migration_role))
        )

    try:
        statement = _provisioning_sql_for_test(
            migration_role=migration_role,
            runtime_role=runtime_role,
            database_name=database_name,
            break_required_structure_relation=True,
        )
        with pytest.raises(DatabaseError), connection.cursor() as cursor:
            cursor.execute(statement)
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
                (runtime_role,),
            )
            assert cursor.fetchone() == (False,)
        assert _public_privilege_snapshot() == public_snapshot
    finally:
        if connection.connection is not None:
            connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(migration_role))
            )
            cursor.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(migration_role))
            )
        _restore_public_privileges(public_snapshot)


@pytest.mark.django_db(transaction=True)
def test_provisioning_artifact_commits_completely_or_rolls_back_completely() -> None:
    """Execute the operator artifact, including one deliberately late failure."""

    public_snapshot = _public_privilege_snapshot()
    database_name, _schema_names = _database_and_user_schemas()
    migration_role = _name("migration")
    runtime_role = _name("runtime")
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(migration_role))
        )

    try:
        failing_statement = _provisioning_sql_for_test(
            migration_role=migration_role,
            runtime_role=runtime_role,
            database_name=database_name,
            break_late_function=True,
        )
        with pytest.raises(DatabaseError), connection.cursor() as cursor:
            cursor.execute(failing_statement)
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
                (runtime_role,),
            )
            assert cursor.fetchone() == (False,)
        assert _public_privilege_snapshot() == public_snapshot

        statement = _provisioning_sql_for_test(
            migration_role=migration_role,
            runtime_role=runtime_role,
            database_name=database_name,
        )
        with connection.cursor() as cursor:
            cursor.execute(statement)

        result = probe_runtime_database_role_safety(role_name=runtime_role)
        assert result.target_role_is_safe
        assert not result.current_session_is_safe
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    pg_catalog.has_database_privilege(
                        %s, pg_catalog.current_database(), 'CONNECT'
                    ),
                    pg_catalog.has_database_privilege(
                        %s, pg_catalog.current_database(), 'CREATE'
                    ),
                    pg_catalog.has_database_privilege(
                        %s, pg_catalog.current_database(), 'TEMPORARY'
                    ),
                    pg_catalog.has_schema_privilege(%s, 'public', 'CREATE'),
                    pg_catalog.has_schema_privilege(%s, 'public', 'USAGE')
                """,
                (migration_role,) * 5,
            )
            assert cursor.fetchone() == (True, True, True, True, True)
            for identity in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS:
                cursor.execute(
                    """
                    SELECT
                        pg_catalog.has_table_privilege(%s, %s, 'SELECT'),
                        pg_catalog.has_table_privilege(%s, %s, 'INSERT'),
                        pg_catalog.has_table_privilege(%s, %s, 'UPDATE'),
                        pg_catalog.has_table_privilege(%s, %s, 'DELETE')
                    """,
                    (
                        runtime_role,
                        identity,
                        runtime_role,
                        identity,
                        runtime_role,
                        identity,
                        runtime_role,
                        identity,
                    ),
                )
                assert cursor.fetchone() == (True, False, False, False)
            _assert_structure_relation_privileges(role_name=runtime_role)

        _assert_default_table_privileges(
            migration_role=migration_role,
            runtime_role=runtime_role,
        )
    finally:
        if connection.connection is not None:
            connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
                (runtime_role,),
            )
            if cursor.fetchone() == (True,):
                cursor.execute(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(runtime_role))
                )
                cursor.execute(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(runtime_role))
                )
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
                (migration_role,),
            )
            if cursor.fetchone() == (True,):
                cursor.execute(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(migration_role))
                )
                cursor.execute(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(migration_role))
                )
        _restore_public_privileges(public_snapshot)
