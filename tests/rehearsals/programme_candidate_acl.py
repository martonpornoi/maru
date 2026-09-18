"""Grant declared candidate table/helper operations in the owned empty fixture."""

import psycopg
from psycopg import sql

from tests.rehearsals.programme_function_acl import (
    grant_candidate_helpers,
    require_helper_catalog,
)
from tests.rehearsals.programme_function_contract import ProgrammeFunctionError
from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    _verify_lease,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)
from tests.rehearsals.programme_runtime_privileges import (
    PRIVILEGES,
    candidate_relation_classes,
)


def install_candidate_table_privileges(lease):
    """Apply explicit DML after canonical ACLs and before any fixture edition.

    Parameters
    ----------
    lease
        Exact still-owned disposable resource, never an arbitrary database URL.

    Notes
    -----
    Caller first proves canonical runtime safety through its genuine login.
    This transaction then requires a fresh empty candidate schema and entirely
    read-only target tables. A separate genuine candidate runtime probe must pass
    after commit. Failure disposes the owned resource; no partial retry/adoption.
    """
    request = require_programme_rehearsal_request()
    _verify_lease(lease, request)
    candidate_relation_classes()
    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=lease.port,
            dbname=lease.database_name,
            user="postgres",
            password=lease.admin_password,
            connect_timeout=5,
            options="-c search_path=pg_catalog -c statement_timeout=30000",
        ) as connection:
            row = connection.execute(
                "SELECT current_database(), session_user, current_user, "
                "current_setting('server_version_num')::integer"
            ).fetchone()
            if (
                row is None
                or row[:3] != (lease.database_name, "postgres", "postgres")
                or not 170000 <= row[3] < 180000
            ):
                raise ProgrammeProvisioningError("candidate_acl_identity_mismatch")
            connection.execute(
                "LOCK TABLE public.events_eventedition IN ACCESS EXCLUSIVE MODE"
            )
            if connection.execute(
                "SELECT EXISTS (SELECT 1 FROM public.events_eventedition), "
                "EXISTS (SELECT 1 FROM public.django_migrations "
                "WHERE app = 'events' AND name = '0015_isolated_programme_candidate')"
            ).fetchone() != (False, True):
                raise ProgrammeProvisioningError("candidate_acl_schema_unavailable")
            if connection.execute(
                "SELECT count(*) = %s AND bool_and("
                "pg_catalog.has_table_privilege('maru_runtime', "
                "relation.oid, 'SELECT') "
                "AND NOT pg_catalog.has_table_privilege('maru_runtime', relation.oid, "
                "'INSERT, UPDATE, DELETE, REFERENCES, TRIGGER, TRUNCATE, MAINTAIN') "
                "AND NOT pg_catalog.has_any_column_privilege('maru_runtime', "
                "relation.oid, 'INSERT, UPDATE, REFERENCES')) "
                "FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' AND relation.relkind = 'r' "
                "AND ('public.' || relation.relname) = ANY(%s)",
                [len(PRIVILEGES), sorted(PRIVILEGES)],
            ).fetchone() != (True,):
                raise ProgrammeProvisioningError("candidate_acl_baseline_changed")
            require_helper_catalog(connection, runtime_granted=False)
            for privileges in sorted(set(PRIVILEGES.values())):
                tables = sorted(
                    table for table, value in PRIVILEGES.items() if value == privileges
                )
                connection.execute(
                    sql.SQL("GRANT {} ON TABLE {} TO maru_runtime").format(
                        sql.SQL(", ").join(sql.SQL(value) for value in privileges),
                        sql.SQL(", ").join(
                            sql.Identifier(*table.split(".")) for table in tables
                        ),
                    )
                )
            grant_candidate_helpers(connection)
            _verify_lease(lease, request)
    except ProgrammeFunctionError:
        raise ProgrammeProvisioningError(
            "candidate_helper_contract_unavailable"
        ) from None
    except psycopg.Error:
        raise ProgrammeProvisioningError("candidate_acl_installation_failed") from None
