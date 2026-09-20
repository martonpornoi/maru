"""Observe the native invitation writer generation, never a code-only flag."""

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module
from typing import Final

from django.db import DatabaseError, connection

from maru.core.database_integrity_readiness import (
    build_database_integrity_contract,
)

INVITATION_WRITER_GENERATION: Final = "identity-invitation-writers-v1"
_SOURCE = "maru.identity.migrations.0023_invitation_writer_cutover"
_SOURCE_SHA256 = "459616cddbb279e5a37ce3aa852d56c437bce1031c2291c09773468a7bd80b32"
_BASE = build_database_integrity_contract(
    status_key="identity_invitation_writers",
    app_label="identity",
    source_migration=("identity", "0023_invitation_writer_cutover"),
    terminal_migration=("identity", "0023_invitation_writer_cutover"),
    source_migration_module=_SOURCE,
)
INVITATION_WRITER_INTEGRITY_CONTRACT = replace(
    _BASE,
    source_contract_current=(
        _BASE.source_contract_current
        and hashlib.sha256(
            inspect.getsource(import_module(_SOURCE)).replace("\r\n", "\n").encode()
        ).hexdigest()
        == _SOURCE_SHA256
    ),
)


def invitation_writer_generation_is_ready() -> bool:
    """Require actual migration, invoker guard, closed ACL and exact trigger.

    Returns
    -------
    bool
        Whether the observed native writer generation matches current code.
        The additive catalog, keys, workers and policy remain separate gates.
    """
    contract = INVITATION_WRITER_INTEGRITY_CONTRACT
    if not contract.source_contract_current or len(contract.functions) != 1:
        return False
    try:
        function = contract.functions["maru_identity_invitation_writer_guard()"]
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM public.django_migrations
                    WHERE app = %s AND name = %s
                ), p.prosrc, l.lanname::text, p.provolatile::text,
                    p.proparallel::text, p.prosecdef, p.proleakproof,
                    p.proisstrict, p.proretset, p.prokind::text, p.proconfig,
                    pg_catalog.pg_get_function_result(p.oid),
                    p.proowner = r.relowner,
                    NOT EXISTS (
                        SELECT 1 FROM pg_catalog.aclexplode(COALESCE(
                            p.proacl, pg_catalog.acldefault('f', p.proowner)
                        )) acl WHERE acl.grantee <> p.proowner
                    ),
                    tn.nspname::text, r.relname::text, r.relkind::text,
                    t.tgname::text, t.tgtype, t.tgenabled::text,
                    t.tgisinternal, t.tgconstraint <> 0,
                    t.tgdeferrable, t.tginitdeferred,
                    t.tgnargs, t.tgqual IS NULL, t.tgattr::text,
                    pn.nspname::text, p.proname::text,
                    pg_catalog.oidvectortypes(p.proargtypes)
                FROM pg_catalog.pg_trigger t
                JOIN pg_catalog.pg_class r ON r.oid = t.tgrelid
                JOIN pg_catalog.pg_namespace tn ON tn.oid = r.relnamespace
                JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
                JOIN pg_catalog.pg_namespace pn ON pn.oid = p.pronamespace
                JOIN pg_catalog.pg_language l ON l.oid = p.prolang
                WHERE t.tgfoid = pg_catalog.to_regprocedure(
                    'public.maru_identity_invitation_writer_guard()'
                ) OR (tn.nspname = 'public'
                    AND t.tgname = 'maru_identity_invitation_writer')
                """,
                contract.source_migration,
            )
            rows = cursor.fetchall()
        if len(rows) != 1:
            return False
        row = rows[0]
        source_digest = hashlib.sha256(
            row[1].replace("\r\n", "\n").strip().encode()
        ).hexdigest()
        return (
            row[0] is True
            and source_digest == function.source_sha256
            and tuple(row[2:10])
            == (
                function.language,
                function.volatility,
                function.parallel,
                function.security_definer,
                function.leakproof,
                function.strict,
                function.returns_set,
                function.kind,
            )
            and tuple(row[10] or ()) == function.configuration
            and row[11] == function.result
            and tuple(row[12:])
            == (
                True,
                True,
                "public",
                "identity_identitychallenge",
                "r",
                "maru_identity_invitation_writer",
                23,
                "O",
                False,
                False,
                False,
                False,
                0,
                True,
                "",
                "public",
                "maru_identity_invitation_writer_guard",
                "",
            )
        )
    except (DatabaseError, LookupError, TypeError, ValueError, AttributeError):
        return False
