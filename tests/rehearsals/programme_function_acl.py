"""Exact helper ACL preparation inside the already fenced empty-fixture transaction."""

import hashlib

from psycopg import sql

from tests.rehearsals.programme_function_contract import HELPERS, ProgrammeFunctionError

_QUERY = """
SELECT required.identity, procedure.prosrc, language.lanname::text,
       procedure.provolatile::text, procedure.proparallel::text,
       procedure.prosecdef, procedure.proleakproof, procedure.proisstrict,
       procedure.proretset, procedure.prokind::text, procedure.proconfig,
       pg_catalog.pg_get_function_result(procedure.oid),
       pg_catalog.pg_get_userbyid(procedure.proowner) = 'maru_migration'
       AND procedure.proowner = (
           SELECT relowner FROM pg_catalog.pg_class
           WHERE oid = 'public.events_eventedition'::pg_catalog.regclass
       ),
       (
           SELECT count(*) = CASE WHEN %s THEN 2 ELSE 1 END
              AND count(DISTINCT privilege.grantee) = count(*)
              AND bool_or(privilege.grantee = procedure.proowner)
              AND bool_and(
                  privilege.grantor = procedure.proowner
                  AND COALESCE(privilege.grantee = procedure.proowner OR (
                      %s AND privilege.grantee = runtime.oid
                      AND NOT privilege.is_grantable
                      AND runtime.oid <> procedure.proowner
                      AND runtime.rolcanlogin AND NOT runtime.rolsuper
                      AND NOT runtime.rolcreaterole AND NOT runtime.rolcreatedb
                      AND NOT runtime.rolreplication AND NOT runtime.rolbypassrls
                  ), FALSE)
              )
           FROM pg_catalog.aclexplode(COALESCE(
               procedure.proacl,
               pg_catalog.acldefault('f'::pg_catalog."char", procedure.proowner)
           )) AS privilege
           WHERE privilege.privilege_type = 'EXECUTE'
       )
FROM pg_catalog.unnest(%s::text[]) AS required(identity)
LEFT JOIN pg_catalog.pg_proc AS procedure
  ON procedure.oid = pg_catalog.to_regprocedure('public.' || required.identity)
LEFT JOIN pg_catalog.pg_language AS language ON language.oid = procedure.prolang
LEFT JOIN pg_catalog.pg_roles AS runtime ON runtime.rolname = 'maru_runtime'
ORDER BY required.identity
"""


def require_helper_catalog(connection, *, runtime_granted):
    """Verify every literal helper body, attribute, owner and exact execution ACL."""
    rows = connection.execute(
        _QUERY, [runtime_granted, runtime_granted, sorted(HELPERS)]
    ).fetchall()
    if len(rows) != len(HELPERS) or {row[0] for row in rows} != HELPERS.keys():
        raise ProgrammeFunctionError("candidate_helper_inventory_changed")
    for row in rows:
        source = str(row[1] or "").replace("\r\n", "\n").strip()
        metadata = (
            hashlib.sha256(source.encode()).hexdigest(),
            *row[2:10],
            tuple(row[10] or ()),
            row[11],
        )
        if metadata != HELPERS[row[0]].metadata or row[12:] != (True, True):
            raise ProgrammeFunctionError("candidate_helper_catalog_changed")


def grant_candidate_helpers(connection):
    """Grant the closed signatures and recheck the installed result before commit.

    Notes
    -----
    Caller must already have verified the lease, empty candidate schema, canonical
    table ACLs and owner-only helper catalog in this same transaction. All names
    and argument types below are trusted literals, never user/fixture inputs.
    """
    signatures = []
    for identity in sorted(HELPERS):
        name, arguments = identity[:-1].split("(", 1)
        signatures.append(
            sql.SQL("{}({})").format(sql.Identifier("public", name), sql.SQL(arguments))
        )
    connection.execute(
        sql.SQL("GRANT EXECUTE ON FUNCTION {} TO maru_runtime").format(
            sql.SQL(", ").join(signatures)
        )
    )
    require_helper_catalog(connection, runtime_granted=True)
